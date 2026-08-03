"""Experimentation platform.

Runs reproducible experiments across A/B tests, feature flags, prompts, rules,
scoring / LLM / supplier / prediction comparisons. It tracks the **winner**,
**confidence**, **profit impact**, **ROI impact**, **precision**, **recall**,
**false positives** and **false negatives**, and generates **experiment reports**.

Reproducibility is enforced end-to-end: variant assignment is a pure function of
``(seed, subject_key)``, statistics are pure functions of the stored
observations, and every experiment captures a config + code-version snapshot at
start with every report storing its full params snapshot.

The pure statistics live in `engine.py` (z-test, Welch's t-test with an exact
t CDF, confusion metrics, deterministic assignment, winner determination,
sample-size planning). Persistence lives in the repository, and the
`ExperimentManager` facade ties them together.
"""

from app.experiments.config import ExperimentConfig
from app.experiments.engine import (
    assign_variant,
    confusion_metrics,
    determine_winner,
    normal_cdf,
    required_sample_size,
    simulate_ab,
    two_proportion_ztest,
    variant_stats,
    welch_ttest,
)
from app.experiments.errors import (
    ExperimentConflictError,
    ExperimentError,
    ExperimentNotFoundError,
    ExperimentValidationError,
)
from app.experiments.manager import ExperimentManager
from app.experiments.models import (
    Assignment,
    Experiment,
    ExperimentReport,
    ExperimentStatus,
    ExperimentType,
    Observation,
    PrimaryMetric,
    Variant,
)
from app.experiments.repository import ExperimentRepository
from app.experiments.schemas import (
    AssignmentRead,
    AssignmentRequest,
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

__all__ = [
    "Assignment",
    "AssignmentRead",
    "AssignmentRequest",
    "Experiment",
    "ExperimentCapabilities",
    "ExperimentConfig",
    "ExperimentConflictError",
    "ExperimentCreate",
    "ExperimentDetail",
    "ExperimentError",
    "ExperimentList",
    "ExperimentManager",
    "ExperimentNotFoundError",
    "ExperimentRead",
    "ExperimentReport",
    "ExperimentRepository",
    "ExperimentStats",
    "ExperimentStatus",
    "ExperimentType",
    "ExperimentUpdate",
    "ExperimentValidationError",
    "Observation",
    "ObservationBatch",
    "ObservationCreate",
    "ObservationList",
    "ObservationRead",
    "PrimaryMetric",
    "ReportList",
    "ReportRead",
    "ResultsRead",
    "SimulateRequest",
    "Variant",
    "VariantCreate",
    "VariantRead",
    "WinnerRead",
    "assign_variant",
    "confusion_metrics",
    "determine_winner",
    "normal_cdf",
    "required_sample_size",
    "simulate_ab",
    "two_proportion_ztest",
    "variant_stats",
    "welch_ttest",
]
