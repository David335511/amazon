"""Experimentation platform API.

The router talks ONLY to `ExperimentManager` (via DI); it contains no statistics
logic. It exposes experiment lifecycle, variants, deterministic assignment,
observation recording (single + batch), live results, winner, precision/recall,
report generation and listing, plus capabilities, stats, templates and a
reproducible A/B simulator for planning.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_experiment_manager
from app.experiments import (
    AssignmentRead,
    AssignmentRequest,
    ExperimentCapabilities,
    ExperimentCreate,
    ExperimentDetail,
    ExperimentList,
    ExperimentManager,
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
from app.experiments.errors import (
    ExperimentConflictError,
    ExperimentNotFoundError,
    ExperimentValidationError,
)

router = APIRouter(prefix="/experiments", tags=["experiments"])

ManagerDep = Annotated[ExperimentManager, Depends(get_experiment_manager)]

TEMPLATES: dict[str, dict] = {
    "ab_test": {
        "name": "A/B conversion test",
        "primary_metric": "conversion",
        "description": "Compare two variants' conversion rate.",
    },
    "feature_flag": {
        "name": "Feature flag rollout",
        "primary_metric": "conversion",
        "description": "Test a feature on/off against a control.",
    },
    "prompt": {
        "name": "Prompt testing",
        "primary_metric": "conversion",
        "description": "Compare prompt variants on an outcome metric.",
    },
    "rule": {
        "name": "Rule testing",
        "primary_metric": "conversion",
        "description": "Compare decision-rule variants on an outcome metric.",
    },
    "scoring_comparison": {
        "name": "Scoring comparison",
        "primary_metric": "precision",
        "description": "Compare scoring functions on precision/recall.",
    },
    "llm_comparison": {
        "name": "LLM comparison",
        "primary_metric": "accuracy",
        "description": "Compare models/prompts on accuracy.",
    },
    "supplier_comparison": {
        "name": "Supplier comparison",
        "primary_metric": "profit",
        "description": "Compare suppliers on profit / ROI.",
    },
    "prediction_comparison": {
        "name": "Prediction comparison",
        "primary_metric": "precision",
        "description": "Compare prediction methods on precision/recall/FP/FN.",
    },
}


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExperimentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ExperimentConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/capabilities", response_model=ExperimentCapabilities)
async def capabilities(manager: ManagerDep) -> ExperimentCapabilities:
    """Supported experiment types, metrics, statuses and tracking capabilities."""
    return manager.capabilities()


@router.get("/stats", response_model=ExperimentStats)
async def stats(manager: ManagerDep) -> ExperimentStats:
    """Platform-wide aggregation of experiments, variants, observations, reports."""
    return await manager.stats()


@router.get("/templates")
async def templates() -> dict[str, dict]:
    """Bundled experiment-type templates with default metrics."""
    return TEMPLATES


@router.post("/simulate", response_model=dict)
async def simulate(body: SimulateRequest, manager: ManagerDep) -> dict:
    """Deterministically simulate a prospective A/B test (reproducible planning)."""
    return await manager.simulate(body)


@router.post("", response_model=ExperimentRead, status_code=status.HTTP_201_CREATED)
async def create_experiment(body: ExperimentCreate, manager: ManagerDep) -> ExperimentRead:
    """Create an experiment (draft) with its initial variants."""
    try:
        return await manager.create_experiment(body)
    except ExperimentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("", response_model=ExperimentList)
async def list_experiments(
    manager: ManagerDep,
    experiment_type: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ExperimentList:
    """List experiments, optionally filtered by type / status."""
    return await manager.list_experiments(
        experiment_type=experiment_type, status=status_, limit=limit, offset=offset,
    )


@router.get("/{experiment_id}", response_model=ExperimentDetail)
async def get_experiment(experiment_id: UUID, manager: ManagerDep) -> ExperimentDetail:
    """Experiment + variants + current live results."""
    try:
        return await manager.get_experiment(experiment_id)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{experiment_id}", response_model=ExperimentRead)
async def update_experiment(
    experiment_id: UUID, body: ExperimentUpdate, manager: ManagerDep
) -> ExperimentRead:
    """Update mutable fields of a draft experiment."""
    try:
        return await manager.update_experiment(experiment_id, body)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ExperimentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experiment(experiment_id: UUID, manager: ManagerDep) -> None:
    """Delete an experiment (cascades to variants, assignments, observations, reports)."""
    try:
        deleted = await manager.delete_experiment(experiment_id)
        if not deleted:
            raise ExperimentNotFoundError(f"Experiment {experiment_id} not found")
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{experiment_id}/variants", response_model=VariantRead)
async def add_variant(experiment_id: UUID, body: VariantCreate, manager: ManagerDep) -> VariantRead:
    """Add a variant (draft only)."""
    try:
        return await manager.add_variant(experiment_id, body)
    except ExperimentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ExperimentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{experiment_id}/start", response_model=ExperimentRead)
async def start(experiment_id: UUID, manager: ManagerDep) -> ExperimentRead:
    """Start the experiment: snapshot config + code version, set running."""
    try:
        return await manager.start(experiment_id)
    except ExperimentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ExperimentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{experiment_id}/stop", response_model=ReportRead)
async def stop(experiment_id: UUID, manager: ManagerDep) -> ReportRead:
    """Stop the experiment and generate its winner/impact report."""
    try:
        return await manager.stop(experiment_id)
    except ExperimentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{experiment_id}/assign", response_model=AssignmentRead)
async def assign(
    experiment_id: UUID, body: AssignmentRequest, manager: ManagerDep
) -> AssignmentRead:
    """Deterministically assign a subject to a variant (idempotent)."""
    try:
        return await manager.assign(experiment_id, body.subject_key)
    except ExperimentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ExperimentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{experiment_id}/observations", response_model=ObservationRead)
async def record(experiment_id: UUID, body: ObservationCreate, manager: ManagerDep) -> ObservationRead:
    """Record one outcome for a subject (auto-assigns if not yet assigned)."""
    try:
        return await manager.record(experiment_id, body)
    except ExperimentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ExperimentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{experiment_id}/observations/batch", response_model=list[ObservationRead])
async def record_many(
    experiment_id: UUID, body: ObservationBatch, manager: ManagerDep
) -> list[ObservationRead]:
    """Record many outcomes at once (deduplicated per subject)."""
    try:
        return await manager.record_many(experiment_id, body)
    except ExperimentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ExperimentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{experiment_id}/observations", response_model=ObservationList)
async def list_observations(
    experiment_id: UUID, manager: ManagerDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ObservationList:
    """List recorded observations."""
    try:
        return await manager.list_observations(experiment_id, limit=limit, offset=offset)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{experiment_id}/results", response_model=ResultsRead)
async def results(experiment_id: UUID, manager: ManagerDep) -> ResultsRead:
    """Live per-variant stats + current winner for the experiment."""
    try:
        return await manager.results(experiment_id)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{experiment_id}/winner", response_model=WinnerRead)
async def winner(experiment_id: UUID, manager: ManagerDep) -> WinnerRead:
    """The current winner + confidence (None if not yet significant)."""
    try:
        return await manager.winner(experiment_id)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{experiment_id}/precision-recall", response_model=dict)
async def precision_recall(experiment_id: UUID, manager: ManagerDep) -> dict:
    """Precision / recall / FP / FN per variant (prediction & scoring types)."""
    try:
        return await manager.precision_recall(experiment_id)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{experiment_id}/report", response_model=ReportRead)
async def generate_report(experiment_id: UUID, manager: ManagerDep) -> ReportRead:
    """Generate (and store) a reproducible report from current observations."""
    try:
        return await manager.generate_report(experiment_id)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{experiment_id}/report", response_model=ReportRead)
async def get_report(experiment_id: UUID, manager: ManagerDep) -> ReportRead:
    """Fetch the latest stored report for the experiment."""
    try:
        return await manager.get_report(experiment_id)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{experiment_id}/reports", response_model=ReportList)
async def list_reports(
    experiment_id: UUID, manager: ManagerDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ReportList:
    """List all generated reports for the experiment (newest first)."""
    try:
        return await manager.list_reports(experiment_id, limit=limit, offset=offset)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
