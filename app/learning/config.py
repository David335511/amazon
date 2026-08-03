"""Continuous-learning platform configuration."""

from __future__ import annotations

from pydantic import BaseModel


class LearningConfig(BaseModel):
    """Configuration for the continuous-learning platform.

    Every value feeds into deterministic, versioned analyses — the same stored
    outcomes always reproduce the same metrics, issues, and recommendations.
    """

    enabled: bool = True
    # Minimum number of resolved outcomes before a (decision, model) group is
    # eligible for issue detection and auto-improvement.
    min_samples_for_issues: int = 5
    # Composite severity (normalised MAE + missed directional accuracy) above
    # which an issue is flagged.
    issue_severity_threshold: float = 0.4
    # Rolling-accuracy window for the accuracy-over-time dashboard series.
    rolling_window: int = 20
    # Rule auto-tuning tolerances.
    default_rule_threshold: float = 0.5
    rule_tune_min_delta: float = 0.01
    rule_tune_min_improvement: float = 0.02
    # Feature re-weighting: minimum absolute correlation between a feature and
    # the prediction error before a reweight is proposed.
    feature_reweight_min_abs_corr: float = 0.2
    # Cap on how many predictions a single scan/cycle examines (newest first).
    max_predictions_per_scan: int = 5000
    # Cap on recommendations persisted per cycle.
    max_recommendations_per_run: int = 50
    # Version of the learning engine code (snapshot for reproducibility).
    code_version: str = ""

    @property
    def as_snapshot(self) -> dict:
        """A JSON-serialisable snapshot of the config (reproducibility)."""
        return self.model_dump()
