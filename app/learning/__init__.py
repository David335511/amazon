"""Continuous-learning platform."""

from app.learning.config import LearningConfig
from app.learning.manager import LearningManager
from app.learning.models import (
    DecisionType,
    IssueType,
    LearningPrediction,
    LearningRecommendation,
    LearningRun,
    PredictionType,
    RecommendationTarget,
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

__all__ = [
    "AccuracyRead",
    "ComparisonRead",
    "DashboardRead",
    "DecisionType",
    "IssueType",
    "LearningCapabilities",
    "LearningConfig",
    "LearningManager",
    "LearningPrediction",
    "LearningRecommendation",
    "LearningRepository",
    "LearningRun",
    "LearningStats",
    "ModelAccuracy",
    "OutcomeCreate",
    "PredictionCreate",
    "PredictionList",
    "PredictionRead",
    "PredictionType",
    "RecommendationList",
    "RecommendationRead",
    "RecommendationTarget",
    "RecommendationUpdate",
    "ReweightResult",
    "RuleTuneResult",
    "RunList",
    "RunRead",
]
