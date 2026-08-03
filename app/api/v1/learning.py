"""Continuous-learning platform API.

The router talks ONLY to `LearningManager` (via DI); it contains no statistics
logic. It exposes prediction recording, outcome feedback, predicted-vs-actual
comparison, accuracy-over-time, the accuracy dashboard, automatic issue
scanning, deterministic rule tuning / feature reweighting, versioned
continuous-learning cycles, and improvement recommendations.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_learning_manager
from app.learning import (
    AccuracyRead,
    ComparisonRead,
    DashboardRead,
    LearningCapabilities,
    LearningManager,
    LearningStats,
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
from app.learning.errors import (
    LearningNotFoundError,
    LearningValidationError,
)

router = APIRouter(prefix="/learning", tags=["learning"])

ManagerDep = Annotated[LearningManager, Depends(get_learning_manager)]


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LearningNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/capabilities", response_model=LearningCapabilities)
async def capabilities(manager: ManagerDep) -> LearningCapabilities:
    """Supported prediction/decision types, recommendation targets and metrics."""
    return manager.capabilities()


@router.get("/stats", response_model=LearningStats)
async def stats(manager: ManagerDep) -> LearningStats:
    """Platform-wide aggregates (predictions, outcomes, recommendations, runs)."""
    return await manager.stats()


@router.post("/predictions", response_model=PredictionRead, status_code=status.HTTP_201_CREATED)
async def record_prediction(body: PredictionCreate, manager: ManagerDep) -> PredictionRead:
    """Record a prediction (idempotent via external_id)."""
    try:
        return await manager.record_prediction(body)
    except LearningValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/outcomes", response_model=dict)
async def record_outcome(body: OutcomeCreate, manager: ManagerDep) -> dict:
    """Record a realised outcome on matching unresolved prediction(s)."""
    updated = await manager.record_outcome(body)
    return {"updated": updated}


@router.get("/predictions", response_model=PredictionList)
async def list_predictions(
    manager: ManagerDep,
    prediction_type: str | None = None,
    decision_type: str | None = None,
    model_version: str | None = None,
    resolved_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PredictionList:
    """List stored predictions, optionally filtered."""
    return await manager.list_predictions(
        prediction_type=prediction_type,
        decision_type=decision_type,
        model_version=model_version,
        resolved_only=resolved_only,
        limit=limit,
        offset=offset,
    )


@router.get("/comparison", response_model=list[ComparisonRead])
async def comparison(manager: ManagerDep) -> list[ComparisonRead]:
    """Predicted vs actual for profit, sales, ROI and risk."""
    return await manager.comparison()


@router.get("/accuracy", response_model=AccuracyRead)
async def accuracy(
    manager: ManagerDep,
    prediction_type: str = Query(...),
    model_version: str | None = None,
) -> AccuracyRead:
    """Accuracy summary + rolling series for a metric (and optional model)."""
    try:
        return await manager.accuracy(prediction_type, model_version=model_version)
    except LearningValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("/dashboard", response_model=DashboardRead)
async def dashboard(manager: ManagerDep) -> DashboardRead:
    """Model-accuracy-over-time dashboard (overall + per metric + per model)."""
    return await manager.dashboard()


@router.post("/scan/issues", response_model=list[dict])
async def scan_issues(manager: ManagerDep) -> list[dict]:
    """Automatically detect bad rules, weak prompts, poor decisions, incorrect
    matches and ranking mistakes from resolved outcomes (no persistence)."""
    return await manager.scan_issues()


@router.post("/optimize/rule-threshold", response_model=RuleTuneResult)
async def optimize_rule(decision_id: str, manager: ManagerDep) -> RuleTuneResult:
    """Deterministically tune a rule's classification threshold."""
    try:
        return await manager.optimize_rule(decision_id)
    except LearningNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/reweight/feature", response_model=ReweightResult)
async def reweight(
    feature: str,
    values: list[float],
    errors: list[float],
    current_weight: float,
    manager: ManagerDep,
) -> ReweightResult:
    """Suggest a new weight for a feature from its correlation with error."""
    return await manager.reweight(
        feature=feature, values=values, errors=errors, current_weight=current_weight,
    )


@router.post("/cycle", response_model=RunRead)
async def run_cycle(manager: ManagerDep) -> RunRead:
    """Run (and persist) a versioned continuous-learning cycle."""
    try:
        return await manager.run_cycle()
    except LearningValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("/runs", response_model=RunList)
async def list_runs(
    manager: ManagerDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RunList:
    """List versioned learning runs (newest first)."""
    return await manager.list_runs(limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: UUID, manager: ManagerDep) -> RunRead:
    """Fetch a learning run (metrics, issues, recommendations, tuning)."""
    try:
        return await manager.get_run(run_id)
    except LearningNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/recommendations", response_model=RecommendationList)
async def list_recommendations(
    manager: ManagerDep,
    status_: str | None = Query(default=None, alias="status"),
    target_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> RecommendationList:
    """List improvement recommendations (open/applied/dismissed)."""
    return await manager.list_recommendations(
        status=status_, target_type=target_type, limit=limit, offset=offset,
    )


@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationRead)
async def update_recommendation(
    recommendation_id: UUID, body: RecommendationUpdate, manager: ManagerDep
) -> RecommendationRead:
    """Mark a recommendation applied or dismissed."""
    try:
        return await manager.update_recommendation(recommendation_id, body)
    except LearningNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LearningValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/report", response_model=dict)
async def generate_report(manager: ManagerDep) -> dict:
    """Generate a markdown continuous-learning report."""
    return {"report": await manager.generate_report()}
